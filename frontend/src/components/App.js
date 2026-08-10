import React, { Component } from 'react';
import { render } from 'react-dom';
import {
  Card, CardTitle, CardBody,
  CardText, Button, CardHeader, CardFooter
} from 'reactstrap';

class App extends Component {
  constructor(props) {
    super(props);
    this.state = {
      elements: [],
      curr_page: 1,
      has_previous: false,
      has_next: true,
      loading: true,
      error: null
    };
    this.handlePageChange(this.state.curr_page);
  }

  async handlePageChange(page_number) {
    this.setState({ loading: true, error: null });
    try {
      const data = new FormData();
      data.append('page_number', page_number);
      const options = {
        method: 'POST',
        body: data
      };
      let elements = [];

      const art_data = await fetch('get_article_data/', options);
      if (!art_data.ok) throw new Error('Failed to fetch article data.');

      const art_res = await art_data.json();

      for (let id of art_res.id) {
        const det_data = await fetch(`article_api/${id}/`);
        if (!det_data.ok) continue;  // Skip this iteration if fetch fails

        const det_res = await det_data.json();
        elements.push(det_res);
      }

      this.setState({
        has_previous: art_res.has_previous,
        has_next: art_res.has_next,
        total: art_res.total,
        elements: elements,
        curr_page: page_number,
        loading: false
      });
    } catch (error) {
      this.setState({ error: error.toString(), loading: false });
    }
  }

  render() {
    const { loading, error, elements, has_previous, has_next, curr_page, total } = this.state;

    if (loading) return <div>Loading...</div>;
    if (error) return <div>Error: {error}</div>;

    return (
      <div id="card_div">
        <Card className="text-white bg-info">
          <CardHeader className="text-center mt-3" style={{ fontSize: "1.2em", fontFamily: '"Comic Sans MS", cursive, sans-serif' }}>
            Top Rated Documents
          </CardHeader>
          <CardBody className="bg-light text-dark">
            <div className="row">
              {elements.map(article => (
                <div className="col-12 my-2 border-bottom d-flex" key={article.pk}>
                  <p>{article.title}</p>
                  <a href={`article/${article.pk}/`} className="ml-auto mr-2">&#8594;</a>
                </div>
              ))}
            </div>
          </CardBody>
          <CardFooter>
            <nav aria-label="Page navigation example" className="d-flex">
              <ul className="pagination mx-auto">
                {has_previous && (
                  <>
                    <li className="page-item"><a className="page-link" onClick={() => this.handlePageChange(1)} href="#"><span aria-hidden="true">&laquo;</span></a></li>
                    <li className="page-item"><a className="page-link" onClick={() => this.handlePageChange(curr_page - 1)} href="#"><span aria-hidden="true">&lt;</span></a></li>
                  </>
                )}
                {curr_page - 1 >= 1 && (
                  <li className="page-item"><a className="page-link" onClick={() => this.handlePageChange(curr_page - 1)} href="#">{curr_page - 1}</a></li>
                )}
                <li className="page-item active"><a className="page-link" href="#">{curr_page}</a></li>
                {curr_page + 1 <= total && (
                  <li className="page-item"><a className="page-link" onClick={() => this.handlePageChange(curr_page + 1)} href="#">{curr_page + 1}</a></li>
                )}
                {has_next && (
                  <>
                    <li className="page-item"><a className="page-link" onClick={() => this.handlePageChange(curr_page + 1)} href="#"><span aria-hidden="true">&gt;</span></a></li>
                    <li className="page-item"><a className="page-link" onClick={() => this.handlePageChange(total)} href="#"><span aria-hidden="true">&raquo;</span></a></li>
                  </>
                )}
              </ul>
            </nav>
          </CardFooter>
        </Card>
      </div>
    );
  }
}

const container = document.getElementById('app');
render(<App />, container);
