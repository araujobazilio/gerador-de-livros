from crewai import Agent, Task, Crew, Process
from dotenv import load_dotenv
# Removendo as ferramentas que podem estar causando problemas
# from crewai_tools import SerperDevTool, DallETool
from langchain_openai import ChatOpenAI
import os
from datetime import datetime
import json
import time

# Função principal para gerar o livro genérico
def gerar_livro_generico(tema, api_key=None, autor=None, email_autor=None, descricao=None, genero=None, estilo=None, publico_alvo=None, callback=None, num_capitulos=12):
    # Carregar variáveis de ambiente
    load_dotenv()
    
    # Configurar a API key da OpenAI
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key

    # Definir valores padrão se não fornecidos
    autor = autor or "Autor Anônimo"
    email_autor = email_autor or "autor@exemplo.com"
    descricao = descricao or f"Um livro sobre {tema}"
    genero = genero or "Ficção"
    estilo = estilo or "Narrativo"
    publico_alvo = publico_alvo or "Adulto"
    ano_atual = datetime.now().year

    # Criar diretório para salvar os capítulos do livro
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    livro_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"livro_{timestamp}")
    os.makedirs(livro_dir, exist_ok=True)
    
    # Arquivo de metadados para o livro
    metadata_file = os.path.join(livro_dir, "metadata.json")
    
    # Criar metadados iniciais
    metadata = {
        "tema": tema,
        "autor": autor,
        "email": email_autor,
        "descricao": descricao,
        "genero": genero,
        "estilo": estilo,
        "publico_alvo": publico_alvo,
        "ano": ano_atual,
        "timestamp": timestamp,
        "capitulos": []
    }
    
    # Salvar metadados iniciais
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    # Definir modelos de IA - usando modelos diferentes para diferentes tarefas
    llm_planejamento = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.7, max_tokens=3000)
    llm_escrita = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.7, max_tokens=4000)
    llm_revisao = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.2, max_tokens=2000)
    
    # Configurações
    # Número de capítulos agora é parâmetro
    # num_capitulos = 12  # Número de capítulos (removido, agora vem do argumento)
    timeout_seconds = 180  # 3 minutos por tarefa
    
    # Meta de palavras
    meta_palavras_total = 27000  # Entre 25.000 e 30.000
    meta_palavras_capitulo = meta_palavras_total // num_capitulos
    total_palavras_livro = 0
    
    # Função para salvar um capítulo em arquivo
    def salvar_capitulo(numero, conteudo):
        arquivo = os.path.join(livro_dir, f"capitulo_{numero}.txt")
        with open(arquivo, 'w', encoding='utf-8') as f:
            f.write(conteudo)
        print(f"Capítulo {numero} salvo em {arquivo}")
        # Atualizar metadados
        metadata["capitulos"].append({
            "numero": numero,
            "arquivo": arquivo,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        return arquivo

    # Função para atualizar o progresso
    def atualizar_progresso(etapa, mensagem):
        if callback:
            callback(etapa, mensagem)
    
    # Atualizar progresso: Iniciando
    atualizar_progresso(1, f"Planejando a estrutura do livro sobre '{tema}'...")

    # FASE 1: GERAR ESTRUTURA E PLANEJAMENTO
    coordenador = Agent(
        role="Planejador e Estruturador de Livros",
        backstory=f"""Especialista em estruturação de livros do gênero {genero} com estilo {estilo}, 
        focado no tema '{tema}'. Conhece os requisitos da Amazon KDP para publicação.""",
        goal=f"""Definir a estrutura do livro sobre '{tema}' com elementos necessários: 
        título, capítulos, personagens e arco narrativo consistente com o gênero {genero} e estilo {estilo}.""",
        verbose=True,
        llm=llm_planejamento,
        max_iterations=3,
        allow_delegation=False
    )

    estrutura_task = Task(
        description=f"""Criar a estrutura do livro sobre '{tema}' do gênero {genero} com estilo {estilo} para o público {publico_alvo}, 
        incluindo título, subtítulo, sumário e personagens.
        
        Desenvolva uma única história contínua ao longo de {num_capitulos} capítulos, com personagens 
        consistentes e um arco narrativo adequado. Para cada capítulo, forneça um título e um resumo 
        detalhado do que acontecerá.""",
        expected_output=f"""Estrutura completa com:
        1. Título e subtítulo do livro
        2. Lista de {num_capitulos} capítulos com títulos e resumos detalhados (pelo menos 3 parágrafos por capítulo)
        3. Personagens principais com descrição de características físicas e psicológicas
        4. Arco narrativo principal completo""",
        agent=coordenador,
        async_execution=False
    )

    atualizar_progresso(2, f"Gerando estrutura do livro sobre '{tema}'...")
    estrutura_crew = Crew(
        agents=[coordenador],
        tasks=[estrutura_task],
        verbose=True
    )
    
    try:
        estrutura_resultado = estrutura_crew.kickoff(inputs={"tema": tema, "genero": genero, "estilo": estilo, "publico_alvo": publico_alvo})
        
        # Salvar estrutura em arquivo
        estrutura_file = os.path.join(livro_dir, "estrutura.txt")
        with open(estrutura_file, 'w', encoding='utf-8') as f:
            f.write(str(estrutura_resultado))
            
        estrutura = str(estrutura_resultado)
        atualizar_progresso(3, f"Estrutura do livro criada com sucesso!")
    except Exception as e:
        print(f"Erro ao gerar estrutura: {str(e)}")
        atualizar_progresso(3, f"Erro ao gerar estrutura: {str(e)}")
        return f"Erro ao gerar estrutura: {str(e)}"

    # FASE 2: GERAR CADA CAPÍTULO INDIVIDUALMENTE
    capitulos_conteudo = []
    
    for i in range(num_capitulos):
        capitulo_num = i + 1
        capitulo_path = os.path.join(livro_dir, f"capitulo_{capitulo_num}.txt")
        if os.path.exists(capitulo_path):
            # Se já existe, carregar o conteúdo para manter continuidade
            with codecs.open(capitulo_path, 'r', encoding='utf-8') as f:
                capitulo_texto = f.read()
            capitulos_conteudo.append(capitulo_texto)
            print(f"Capítulo {capitulo_num} já existe. Pulando geração.")
            atualizar_progresso(4, f"Capítulo {capitulo_num} já existente. Pulando geração.")
            continue

        atualizar_progresso(4, f"Gerando capítulo {capitulo_num} de {num_capitulos}...")
        try:
            # Criar escritor para este capítulo
            escritor = Agent(
                role=f"Escritor do Capítulo {capitulo_num}",
                backstory=f"""Escritor especializado em {genero} com estilo {estilo}, criador de histórias envolventes sobre '{tema}' 
                para o público {publico_alvo}.""",
                goal=f"""Escrever um capítulo completo e cativante, seguindo fielmente a estrutura fornecida e mantendo a continuidade narrativa. 
                Este capítulo deve ter pelo menos {meta_palavras_capitulo} palavras, visando que o livro final tenha entre 25.000 e 30.000 palavras. 
                Mantenha a história coerente, conectada e sem deixar pontas soltas.""",
                verbose=True,
                llm=llm_escrita,
                max_iterations=3,
                allow_delegation=False
            )
            
            # Contexto para o capítulo atual
            contexto = f"""ESTRUTURA DO LIVRO:
            {estrutura}
            
            INSTRUÇÕES PARA ESTE CAPÍTULO:
            Você está escrevendo o Capítulo {capitulo_num} de {num_capitulos}.
            O livro deve ter mais de 100 páginas no total. Cada capítulo deve ser detalhado, extenso e contribuir para que o livro ultrapasse 100 páginas. Escreva capítulos longos, densos e completos, com bastante desenvolvimento de cenas, diálogos e descrições."""
            
            # Adicionar conteúdo dos capítulos anteriores para continuidade
            if capitulo_num > 1:
                contexto += "\nCONTEÚDO DOS CAPÍTULOS ANTERIORES:\n"
                for j in range(len(capitulos_conteudo)):
                    contexto += f"\n--- CAPÍTULO {j+1} ---\n"
                    # Mostrar apenas os primeiros e últimos parágrafos para economizar tokens
                    cap_paragrafos = capitulos_conteudo[j].split('\n\n')
                    if len(cap_paragrafos) > 6:
                        inicio = '\n\n'.join(cap_paragrafos[:3])
                        fim = '\n\n'.join(cap_paragrafos[-3:])
                        contexto += f"\n{inicio}\n\n[...]\n\n{fim}\n"
                    else:
                        contexto += f"\n{capitulos_conteudo[j]}\n"
            
            # Tarefa de escrita para o capítulo
            capitulo_task = Task(
                description=f"""Escrever o Capítulo {capitulo_num} baseado na estrutura e contexto fornecidos.
                
                {contexto}
                
                INSTRUÇÕES IMPORTANTES:
                1. {"Inicie a história apresentando os personagens e o cenário." if capitulo_num == 1 else "Continue exatamente de onde o capítulo anterior parou."}
                2. {"Desenvolva o conflito principal." if 1 < capitulo_num < num_capitulos else ""}
                3. {"Conclua a história com uma resolução satisfatória." if capitulo_num == num_capitulos else "Termine em um ponto que crie expectativa para o próximo capítulo."}
                4. Garanta que o conteúdo seja apropriado para o público {publico_alvo} e siga as convenções do gênero {genero} com estilo {estilo}.
                5. Certifique-se de incluir título e conteúdo.
                6. O capítulo deve ser longo, detalhado e contribuir para que o livro ultrapasse 100 páginas no total. Capriche no desenvolvimento de cenas, diálogos e descrições.
                7. Se o nome do personagem principal for especificado na descrição, use exatamente esse nome em toda a história.

                FORMATAÇÃO PARA KDP (Amazon):
                - Estruture o livro com: página de título, dedicatória (opcional), direitos autorais, sumário/índice, capítulos, sobre o autor (no final).
                - Cada capítulo deve começar em uma nova página e ter o título centralizado (estilo “Título 1”).
                - Utilize fonte clara e legível (Times New Roman ou Arial, tamanho 12), texto justificado, recuo de 5 mm na primeira linha de cada parágrafo, espaçamento simples.
                - Inclua sumário/índice no início, com os títulos dos capítulos.
                - Se inserir imagens, use apenas como ilustração e indique onde elas devem aparecer.
                - Adicione, se possível, uma breve seção “Sobre o autor” ao final.
                - Siga rigorosamente as normas de formatação para publicação na Amazon KDP.
                """,
                expected_output=f"""O capítulo {capitulo_num} completo com título e conteúdo, seguindo todas as instruções.
                Deve ter tamanho adequado (mínimo de 1000 palavras) e ser estruturado em parágrafos.""",
                agent=escritor
            )
            
            # Criar crew para gerar o capítulo
            capitulo_crew = Crew(
                agents=[escritor],
                tasks=[capitulo_task],
                verbose=True
            )
            
            # Gerar o capítulo
            capitulo_resultado = capitulo_crew.kickoff()
            capitulo_texto = str(capitulo_resultado)
            
            # Contar palavras do capítulo
            qtd_palavras = len(capitulo_texto.split())
            total_palavras_livro += qtd_palavras
            print(f"Capítulo {capitulo_num} gerado com {qtd_palavras} palavras.")
            atualizar_progresso(4, f"Capítulo {capitulo_num} gerado com {qtd_palavras} palavras.")
            
            # Salvar o capítulo em arquivo
            salvar_capitulo(capitulo_num, capitulo_texto)
            
            # Armazenar o conteúdo do capítulo
            capitulos_conteudo.append(capitulo_texto)
            
            # Pequena pausa para evitar rate limiting
            time.sleep(2)
            
        except Exception as e:
            print(f"Erro ao gerar capítulo {capitulo_num}: {str(e)}")
            atualizar_progresso(4, f"Erro ao gerar capítulo {capitulo_num}: {str(e)}")
            capitulos_conteudo.append(f"[ERRO NO CAPÍTULO {capitulo_num}: {str(e)}]")
            continue
    
    # FASE 3: COMPILAR O LIVRO COMPLETO
    atualizar_progresso(5, f"Compilando livro completo...")
    
    try:
        # Criar o livro completo
        livro_completo = f"""# {tema.upper()}

## Livro

Por {autor}

Copyright {ano_atual} {autor}
Todos os direitos reservados.

---

{estrutura}

---

"""
        
        # Adicionar cada capítulo
        for i, capitulo in enumerate(capitulos_conteudo):
            livro_completo += f"\n\n## Capítulo {i+1}\n\n{capitulo}\n\n---\n"
        
        # Adicionar informações do autor
        livro_completo += f"""
## Sobre o Autor

{autor} é um autor de livros apaixonado por criar histórias mágicas que inspiram e educam.

Para contato: {email_autor}

Este livro foi gerado com assistência de Inteligência Artificial para publicação na Amazon KDP.
"""
        
        # Salvar o livro completo
        livro_file = os.path.join(livro_dir, "livro_completo.txt")
        with open(livro_file, 'w', encoding='utf-8') as f:
            f.write(livro_completo)
        
        atualizar_progresso(6, f"Livro '{tema}' finalizado com sucesso! Salvo em {livro_file}")
        
        return livro_completo
        
    except Exception as e:
        print(f"Erro ao compilar livro: {str(e)}")
        atualizar_progresso(6, f"Erro ao compilar livro: {str(e)}")
        return livro_completo

# Executar diretamente apenas se o script for chamado diretamente
if __name__ == "__main__":
    tema_padrao = "Aventuras no Mundo Mágico"
    livro = gerar_livro_generico(tema_padrao)
    print(livro)
